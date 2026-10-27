# -*- coding: utf-8 -*-
"""Texas sales tax: what each client owes, and the presses that collect it.

The accountant's reading: software sold as a service is a data processing
service, 80% of it taxable, so 8.25% x 80% = 6.6% of every dollar billed. Most
invoices went out without it, so every client carries a balance of tax they
were never charged, and that balance is what this proves gets worked out right.

What is proved:

  1. The rate is 6.6 exactly, not 6.6000000000000005, because it becomes a
     Stripe tax rate and Stripe would print the noise.
  2. A sent or paid invoice with no tax owes 6.6% of it; one charged at the
     rate owes nothing, and a cent or two of Stripe's per-line rounding is
     not a balance.
  3. A draft is not a sale, but it IS flagged when it carries no tax, because
     the year of pre-written drafts is where the hole stays open.
  4. Void, exempt clients, not-taxable invoices and sales before the count
     date are all left out, each with a reason the page can show.
  5. A catch-up invoice is tax, not a sale: nothing is owed ON it, drafting
     one takes its amount off "to bill", and paying it counts as collected.
  6. Per project: the only project gets an unassigned invoice; with two, the
     invoice is left unassigned rather than guessed.
  7. The importer writes the tax, the pre-tax subtotal, the day of sale and
     the catch-up flag, and reads tax on every Stripe API shape.
  8. The pages draw, the presses act on what was pressed, and an invoice the
     board raises carries the tax rate unless the client is exempt.

Run: python tools/test_sales_tax.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-salestax-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Client, Project, Invoice, User, SalesTaxSetting,  # noqa: E402
                    TimeEntry)
import sales_tax  # noqa: E402
import stripe_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def inv(id, total, tax=0.0, status="paid", project_id=None, client_id=1, issued=date(2026, 8, 3),
        catchup=False, exempt=False, paid=None):
    return NS(id=id, total=total, tax=tax, status=status, project_id=project_id, client_id=client_id,
              issued_on=issued, sales_tax_catchup=catchup, sales_tax_exempt=exempt,
              amount_paid=total if paid is None else paid, amount_due=0.0,
              invoice_number=f"000{id}")


def settings(count_from=None):
    return NS(rate_percent=8.25, taxable_share=80.0, count_from=count_from,
              effective_percent=round(8.25 * 80.0 / 100.0, 4))


CLIENT = NS(id=1, name="Kenali Kendrick", stripe_customer_id="cus_k", sales_tax_exempt=False,
            sales_tax_exempt_reason="")
P1 = NS(id=11, client_id=1, name="Talent Booker")
P2 = NS(id=12, client_id=1, name="Workforce")


print("THE RATE:")
with application.app_context():
    db.create_all()
    s = SalesTaxSetting.get()
    check("8.25% on 80% is exactly 6.6", s.effective_percent == 6.6, s.effective_percent)


print("\nWHAT AN INVOICE OWES:")
st = settings()
r = sales_tax.invoice_row(inv(1, 1500.0), st, CLIENT, P1, client_exempt=False)
check("$1,500 with no tax owes $99.00", r["due"] == 99.0 and r["short"] == 99.0, r)
r = sales_tax.invoice_row(inv(2, 1599.0, tax=99.0), st, CLIENT, P1, client_exempt=False)
check("charged at the rate, nothing short", r["base"] == 1500.0 and r["short"] == 0.0, r)
r = sales_tax.invoice_row(inv(3, 1598.97, tax=98.97), st, CLIENT, P1, client_exempt=False)
check("three cents of rounding is not a balance", r["short"] == 0.0, r)
r = sales_tax.invoice_row(inv(4, 50.0, status="open"), st, CLIENT, P1, client_exempt=False)
check("a sent, unpaid invoice is a sale too", r["counted"] and r["short"] == 3.3, r)
r = sales_tax.invoice_row(inv(5, 1500.0, status="draft"), st, CLIENT, P1, client_exempt=False)
check("a draft is not a sale", not r["counted"])
check("but an untaxed draft is flagged", r["draft_missing_tax"])
r = sales_tax.invoice_row(inv(6, 1599.0, tax=99.0, status="draft"), st, CLIENT, P1, client_exempt=False)
check("a taxed draft is not flagged", not r["draft_missing_tax"])
r = sales_tax.invoice_row(inv(7, 1500.0, status="void"), st, CLIENT, P1, client_exempt=False)
check("void is no sale", not r["counted"] and not r["draft_missing_tax"])
r = sales_tax.invoice_row(inv(8, 1500.0, exempt=True), st, CLIENT, P1, client_exempt=False)
check("a not-taxable invoice is left out, and says so", not r["counted"] and r["excluded"] == "not taxable", r)
r = sales_tax.invoice_row(inv(9, 1500.0, issued=date(2025, 12, 1)), settings(date(2026, 1, 1)),
                          CLIENT, P1, client_exempt=False)
check("a sale before the count date is left out", not r["counted"] and r["excluded"].startswith("before"),
      r["excluded"])


print("\nA CLIENT'S BALANCE:")
invoices = [
    inv(1, 1500.0, project_id=11),                 # owes 99.00
    inv(2, 1500.0, project_id=12, status="open"),  # owes 99.00
    inv(3, 50.0),                                  # no project, two to choose from
    inv(4, 1500.0, status="draft"),                # untaxed draft
    inv(5, 1500.0, status="draft"),                # untaxed draft
]
led = sales_tax.build(st, [CLIENT], invoices, [P1, P2])
e = led["clients"][0]
check("never charged is the sum of the shorts", e["short"] == 201.30, e["short"])
check("all of it is left to bill", e["to_bill"] == 201.30, e["to_bill"])
check("two drafts are waiting without tax", len(e["drafts_missing_tax"]) == 2)
names = [(g["project"].name if g["project"] else None) for g in e["groups"]]
check("with two projects, an unassigned invoice is not guessed", names == ["Talent Booker", "Workforce", None], names)
lines = sales_tax.catchup_lines(e)
check("the catch-up has a line per project", len(lines) == 3, lines)
check("and its lines add up to the balance", round(sum(l["unit_amount"] for l in lines), 2) == 201.30)

drafted = invoices + [inv(20, 100.0, status="draft", catchup=True)]
e = sales_tax.build(st, [CLIENT], drafted, [P1, P2])["clients"][0]
check("a drafted catch-up comes off what is left to bill", e["to_bill"] == 101.30 and e["drafted"] == 100.0, e["to_bill"])
check("nothing is owed ON a catch-up", e["short"] == 201.30, e["short"])
check("once something is billed back, the rest is one line", len(sales_tax.catchup_lines(e)) == 1)

paid = invoices + [inv(20, 201.30, catchup=True)]
e = sales_tax.build(st, [CLIENT], paid, [P1, P2])["clients"][0]
check("a paid catch-up counts as collected and clears the balance", e["collected"] == 201.30 and e["to_bill"] == 0.0)
part = invoices + [inv(20, 201.30, status="open", catchup=True, paid=100.0)]
e = sales_tax.build(st, [CLIENT], part, [P1, P2])["clients"][0]
check("a part-paid catch-up is billed in full, not offered again", e["to_bill"] == 0.0, e["to_bill"])

e = sales_tax.build(st, [CLIENT], [inv(1, 1500.0)], [P1])["clients"][0]
check("with one project, an unassigned invoice is that project's", e["groups"][0]["project"] is P1)

EXEMPT = NS(**{**CLIENT.__dict__, "id": 2, "sales_tax_exempt": True})
led = sales_tax.build(st, [CLIENT, EXEMPT], [inv(1, 1500.0), inv(2, 1500.0, client_id=2)], [P1])
check("an exempt client owes nothing", led["clients"][1]["to_bill"] == 0.0)
check("and is not in the totals", led["totals"]["short"] == 99.0, led["totals"])
check("the client who owes sorts first", led["clients"][0]["client"].id == 1)
check("a quarter carries the taxable 80%", led["quarters"][0]["taxable"] == 1200.0, led["quarters"])

subs = [{"id": "sub_1", "customer_id": "cus_k", "rate_ids": []},
        {"id": "sub_2", "customer_id": "cus_k", "rate_ids": ["txr_new"]}]
e = sales_tax.build(st, [CLIENT], [], [P1], subs, "txr_new")["clients"][0]
check("a subscription without the rate is flagged; one with it is not",
      [s["id"] for s in e["subs_missing_tax"]] == ["sub_1"])
e = sales_tax.build(st, [CLIENT], [], [P1], [{"id": "sub_3", "customer_id": "cus_k", "rate_ids": ["txr_old"]}],
                    "txr_new")["clients"][0]
check("one on an old rate is flagged too", len(e["subs_missing_tax"]) == 1)


print("\nTAX ON EVERY STRIPE SHAPE:")
check("total less total_excluding_tax", stripe_service.invoice_tax_cents(NS(total=10660, total_excluding_tax=10000)) == 660)
check("the old `tax` field", stripe_service.invoice_tax_cents(NS(total=10660, tax=660)) == 660)
check("neither is zero, not a crash", stripe_service.invoice_tax_cents(NS(total=10000)) == 0)


print("\nTHE IMPORTER:")
ts = int(datetime(2026, 8, 3, 15, tzinfo=timezone.utc).timestamp())
FAKE = [
    {"id": "in_a", "number": "A-1", "status": "paid", "customer_id": "cus_k", "total": 1599.0, "tax": 99.0,
     "amount_due": 0.0, "amount_paid": 1599.0, "due_date": None, "paid_at": None,
     "issued_at": datetime.fromtimestamp(ts, timezone.utc), "catchup": False},
    {"id": "in_b", "number": "A-2", "status": "void", "customer_id": "cus_k", "total": 99.0, "tax": 0.0,
     "amount_due": 99.0, "amount_paid": 0.0, "due_date": None, "paid_at": None,
     "issued_at": datetime.fromtimestamp(ts, timezone.utc), "catchup": True},
]
stripe_service.get_stripe_invoices = lambda ttl=300: FAKE
with application.app_context():
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    k = Client(name="Kenali Kendrick", email="k@example.test", stripe_customer_id="cus_k")
    x = Client(name="Out Of State Co", email="x@example.test", sales_tax_exempt=True)
    db.session.add_all([boss, k, x])
    db.session.flush()
    db.session.add_all([Project(name="Talent Booker", client_id=k.id), Project(name="Workforce", client_id=k.id)])
    db.session.commit()
    boss_id, k_id, x_id = boss.id, k.id, x.id

    stripe_service.import_invoices_from_stripe()
    a = Invoice.query.filter_by(stripe_invoice_id="in_a").one()
    b = Invoice.query.filter_by(stripe_invoice_id="in_b").one()
    check("tax is written", a.tax == 99.0, a.tax)
    check("the subtotal is the total without the tax", a.subtotal == 1500.0, a.subtotal)
    check("the day of sale is Stripe's, not the import's", a.issued_on == date(2026, 8, 3), a.issued_on)
    check("the catch-up flag comes back from metadata", b.sales_tax_catchup and not a.sales_tax_catchup)
    a.sales_tax_exempt = True
    db.session.commit()
    stripe_service.import_invoices_from_stripe()
    check("an import never clears the board's not-taxable mark",
          db.session.get(Invoice, a.id).sales_tax_exempt)
    a.sales_tax_exempt = False
    # A plain unpaid-tax sale to collect on, assigned to nothing.
    db.session.add(Invoice(client_id=k_id, status="paid", total=1500.0, tax=0.0, subtotal=1500.0,
                           amount_paid=1500.0, issued_on=date(2026, 9, 2), stripe_invoice_id="in_c"))
    db.session.add(Invoice(client_id=k_id, status="draft", total=1500.0, tax=0.0, subtotal=1500.0,
                           issued_on=date(2026, 9, 2), stripe_invoice_id="in_d"))
    db.session.commit()
    c_id = Invoice.query.filter_by(stripe_invoice_id="in_c").one().id


print("\nTHE PAGES:")
calls = []
stripe_service.get_subscriptions_for_tax = lambda ttl=300: [
    {"id": "sub_k", "customer_id": "cus_k", "status": "active", "amount": 50.0, "interval": "month", "rate_ids": []}]
import pm.tax_routes as routes  # noqa: E402
routes.get_subscriptions_for_tax = stripe_service.get_subscriptions_for_tax
routes.import_invoices_from_stripe = lambda ttl=300: (0, 0, ["X-9"])


def fake_rate(s):
    calls.append(("rate", s.effective_percent))
    s.stripe_tax_rate_id, s.stripe_tax_rate_percent = "txr_test", s.effective_percent
    return "txr_test", None


routes.ensure_sales_tax_rate = fake_rate
routes.add_tax_rate_to_draft = lambda sid, rid: calls.append(("draft", sid, rid))
routes.add_tax_rate_to_subscription = lambda sid, rid: calls.append(("sub", sid, rid))
routes.sync_invoice_from_stripe = lambda local: True
routes.create_stripe_invoice = lambda client, lines, **kw: (
    calls.append(("invoice", client.id, lines, kw)) or (NS(id="in_catch"), []))

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)
    sess["_fresh"] = True

r = c.get("/admin/taxes/sales")
page = r.data.decode("utf-8", "replace")
check("the sales tax page draws", r.status_code == 200, r.status_code)
check("it says what is left to bill", "$99.00 to bill" in page)
check("it names the Stripe invoice on no client", "X-9" in page)
check("it offers to tax the subscription", "Tax the subscription" in page)
check("it offers to tax the draft", "Tax 1 draft" in page)
check("the exempt client is not on it, having no invoices", "Out Of State Co" not in page)
check("no em dash on the page", chr(0x2014) not in page)
r = c.get("/admin/taxes/")
check("the income tax page links across", r.status_code == 200 and b"Sales tax" in r.data, r.status_code)

r = c.get(f"/admin/clients/{k_id}")
check("the client page carries the balance", r.status_code == 200 and b"$99.00 to bill" in r.data, r.status_code)

print("\nTHE PRESSES:")
r = c.post(f"/admin/taxes/sales/clients/{k_id}/drafts")
check("taxing drafts touches the untaxed draft and nothing else",
      [x for x in calls if x[0] == "draft"] == [("draft", "in_d", "txr_test")], calls)
r = c.post(f"/admin/taxes/sales/clients/{k_id}/subscriptions")
check("taxing the subscription touches that subscription",
      ("sub", "sub_k", "txr_test") in calls, calls)

r = c.post(f"/admin/taxes/sales/clients/{k_id}/catchup")
made = [x for x in calls if x[0] == "invoice"]
check("the catch-up is drafted for exactly the balance",
      made and round(sum(l["unit_amount"] for l in made[0][2]), 2) == 99.0, made)
check("it is marked as a catch-up in Stripe", made and made[0][3]["metadata"] == {"bbb_sales_tax": "catchup"})
check("and carries no tax of its own", made and not made[0][3].get("tax_rate_ids"))
with application.app_context():
    local = Invoice.query.filter_by(stripe_invoice_id="in_catch").one()
    check("a local catch-up row exists, as a draft", local.sales_tax_catchup and local.status == "draft")
r = c.get("/admin/taxes/sales")
check("after drafting it, nothing is left to bill", b"to bill" not in r.data.split(b"Left to bill")[1][:400]
      or b"$0.00" in r.data.split(b"Left to bill")[1][:400])
calls.clear()
c.post(f"/admin/taxes/sales/clients/{k_id}/catchup")
check("pressing it again drafts nothing", not [x for x in calls if x[0] == "invoice"], calls)

with application.app_context():
    p2 = Project.query.filter_by(name="Workforce").one()
    other = Project(name="Somebody Else's", client_id=x_id)
    db.session.add(other)
    db.session.commit()
    p2_id, other_id = p2.id, other.id
r = c.post(f"/admin/taxes/sales/invoices/{c_id}/project", data={"project_id": p2_id})
with application.app_context():
    check("an invoice can be filed to one of its client's projects",
          db.session.get(Invoice, c_id).project_id == p2_id)
r = c.post(f"/admin/taxes/sales/invoices/{c_id}/project", data={"project_id": other_id})
with application.app_context():
    check("but never to another client's", r.status_code == 400 and db.session.get(Invoice, c_id).project_id == p2_id,
          r.status_code)
c.post(f"/admin/taxes/sales/invoices/{c_id}/taxable")
with application.app_context():
    check("not taxable is a toggle", db.session.get(Invoice, c_id).sales_tax_exempt)
c.post(f"/admin/taxes/sales/invoices/{c_id}/taxable")
c.post(f"/admin/taxes/sales/clients/{k_id}/exempt", data={"reason": "Certificate on file"})
with application.app_context():
    kk = db.session.get(Client, k_id)
    check("a client can be marked exempt, with the reason kept",
          kk.sales_tax_exempt and kk.sales_tax_exempt_reason == "Certificate on file")
c.post(f"/admin/taxes/sales/clients/{k_id}/exempt")
with application.app_context():
    check("and put back", not db.session.get(Client, k_id).sales_tax_exempt)

c.post("/admin/taxes/sales/settings", data={"rate_percent": "8.25", "taxable_share": "80",
                                           "count_from": "2026-01-01"})
with application.app_context():
    s = SalesTaxSetting.get()
    check("the settings save", s.count_from == date(2026, 1, 1) and s.effective_percent == 6.6)


print("\nAN INVOICE THE BOARD RAISES:")
import pm.stripe_routes as sroutes  # noqa: E402
import stripe_service as svc  # noqa: E402
seen = []
sroutes.create_stripe_invoice = lambda client, lines, **kw: (seen.append(kw.get("tax_rate_ids")) or (NS(id=f"in_new{len(seen)}"), []))
sroutes.sync_invoice_from_stripe = lambda local: True
svc.ensure_sales_tax_rate = lambda s: ("txr_test", None)
with application.app_context():
    for cid in (k_id, x_id):
        cl = db.session.get(Client, cid)
        cl.stripe_customer_id = cl.stripe_customer_id or "cus_x"
        p = cl.projects.first()
        db.session.add(TimeEntry(client_id=cid, project_id=p.id, date=date(2026, 10, 1),
                                 hours=1.0, rate_type="development", description="work"))
    db.session.commit()
    entries = {e.client_id: e.id for e in TimeEntry.query.all()}
for cid in (k_id, x_id):
    c.post("/admin/stripe/invoices/new", data={"client_id": cid, "time_entries": entries[cid]})
check("a taxable client's invoice carries the rate", seen[:1] == [["txr_test"]], seen)
check("an exempt client's does not", seen[1:2] == [None], seen)


print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("all passed")
