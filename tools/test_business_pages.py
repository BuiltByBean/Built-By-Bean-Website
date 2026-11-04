# -*- coding: utf-8 -*-
"""The Businesses page shows the business, and the tax lives inside it.

Michael, 2026-11-01: "as my business grows I want these done differently.
Where I can see the business", with the name, the logo, the start date and the
lifetime revenue up front. This boots the board on a throwaway SQLite database
and proves:

  1. The list shows each business's name, start date and lifetime revenue, and
     no WebFile or taxpayer number; each tile opens its business.
  2. Revenue is earned money: paid less its sales tax, nothing from a
     back-tax invoice. The Businesses tile, the Overview's Income (the
     Dashboard's Total Revenue until 2026-11-04) and its Net, the Clients
     list's Paid column and the client page all read
     that same figure (they disagreed the evening this shipped, and then
     Michael chose to take the tax out). The API's "paid" stays cash in.
     A business on its app shows what the app last
     said, the list never asks the app, and the business's page asks only when
     that answer is old. A business with nothing to count says so.
  3. The business's page carries its tax: the numbers, the next return, eSystems.
  4. A logo is an app's icon on My Apps or an uploaded image, one or the other,
     served with the same lock-down headers as My Apps; "none" clears both.
  5. The migration gives each business its app's icon and touches nothing else.

Run: python tools/test_business_pages.py
"""
import importlib.util
import io
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-business-pages-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, AppLink, Business, Client, Invoice, User  # noqa: E402
import pm.business_routes as br  # noqa: E402

br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])   # never touch Stripe from a test
hub_calls = []


def fake_fetch(base_url, path, payload, *, secret, origin_slug, timeout=20):
    hub_calls.append((path, payload, timeout))
    return {"sales": [{"date": "2026-11-06", "total": 1299.0}, {"date": "2026-11-07", "total": 6050.0},
                      {"date": "2026-11-08", "total": "bad"}]}


br.hub.fetch = fake_fetch

# Stripe's invoices as the dashboard and the Businesses page both read them:
# paid with and without tax, a paid back-tax invoice, an open one, a draft.
import stripe_service  # noqa: E402
def _stripe_row(n, status, total, tax, catchup=False):
    """One invoice in the shape stripe_service.get_stripe_invoices returns."""
    when = datetime(2026, 10, n, tzinfo=timezone.utc)
    paid = status == "paid"
    return {"id": f"in_{n}", "number": f"BBB-{n}", "status": status, "customer_id": "cus_1",
            "customer_name": "J&D Entertainment", "total": total, "tax": tax,
            "amount_due": 0.0 if paid else total, "amount_paid": total if paid else 0.0,
            "created_at": when, "due_date": when + timedelta(days=30),
            "paid_at": when if paid else None, "issued_at": when, "catchup": catchup,
            "description": None, "lines": [], "hosted_url": None, "pdf_url": None,
            "admin_url": f"https://dashboard.stripe.com/invoices/in_{n}"}


stripe_service.get_stripe_invoices = lambda ttl=300: [
    _stripe_row(1, "paid", 11350.0, 0.0), _stripe_row(2, "paid", 1066.0, 66.0),
    _stripe_row(3, "paid", 749.10, 0.0, catchup=True), _stripe_row(4, "open", 5000.0, 0.0),
    _stripe_row(5, "draft", 900.0, 0.0)]

application = create_app()
application.config["UPLOAD_FOLDER"] = TMP
application.config["WTF_CSRF_ENABLED"] = False
application.config["GUIDANCE_API_KEY"] = "test-key"
FAIL = []
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 120)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    client = Client(name="J&D Entertainment", email="jd@example.test", stripe_customer_id="cus_1")
    db.session.add_all([boss, client])
    db.session.flush()
    site = AppLink(name="Built By Bean", url="https://builtbybeans.com", icon_file="bbb.png")
    ehq_app = AppLink(name="EntertainHQ", url="https://entertainhq.com", icon_file="ehq.png")
    bare = AppLink(name="No Icon", url="https://noicon.example.test")
    db.session.add_all([site, ehq_app, bare])
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   formed_on=date(2024, 1, 17), texas_taxpayer_number="32093304155",
                   sales_tax_webfile="RT000000", sales_source="board", taxable_share=80.0)
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq",
                   formed_on=date(2026, 10, 5), sales_source="hub", hub_slug="entertainhq",
                   hub_secret="s3cret", hub_base_url="https://ehq.example.test", taxable_share=80.0)
    shelf = Business(name="Shelf Company LLC", slug="shelf", sales_source="manual")
    db.session.add_all([bbb, ehq, shelf])
    db.session.flush()
    for n, (status, total, tax, catchup) in enumerate([
            ("paid", 11350.0, 0.0, False), ("paid", 1066.0, 66.0, False),   # $1,000 sale plus tax
            ("paid", 749.10, 0.0, True),                                     # back tax: not a sale
            ("open", 5000.0, 0.0, False), ("draft", 900.0, 0.0, False)], start=1):
        db.session.add(Invoice(client_id=client.id, status=status, total=total, tax=tax,
                               subtotal=total - tax, amount_paid=total if status == "paid" else 0,
                               issued_on=date(2026, 10, n), sales_tax_catchup=catchup,
                               stripe_invoice_id=f"in_{n}"))
    db.session.commit()
    ids = dict(client=client.id, boss=boss.id, bbb=bbb.id, ehq=ehq.id, shelf=shelf.id, site=site.id,
               ehq_app=ehq_app.id, bare=bare.id)

    print("The migration")
    spec = importlib.util.spec_from_file_location(
        "mig", ROOT / "migrations/versions/c3e9f2a61d84_a_business_wears_its_logo_and_its_revenue.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        mig.upgrade()
    db.session.expire_all()
    check("Built by Bean wears the Built By Bean tile's icon",
          db.session.get(Business, ids["bbb"]).logo_app_id == ids["site"])
    check("EntertainHQ wears the EntertainHQ tile's icon",
          db.session.get(Business, ids["ehq"]).logo_app_id == ids["ehq_app"])
    check("a business with no tile is left alone", db.session.get(Business, ids["shelf"]).logo_app_id is None)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("The list")
html = c.get("/admin/businesses").get_data(as_text=True)
check("shows each business by name", all(n in html for n in ("Built by Bean", "EntertainHQ", "Shelf Company LLC")))
check("with its start date", "Jan 17, 2024" in html and "Oct 05, 2026" in html,
      re.findall(r"[A-Z][a-z]{2} \d{1,2}, 20\d\d", html))
dash = c.get("/admin/finances", follow_redirects=True).get_data(as_text=True)
m = re.search(r"Income.*?(\$[\d,]+\.\d\d)", dash, re.S)
dash_total = m.group(1) if m else None
check("the Overview's Income is paid less tax, no back tax: $12,350.00", dash_total == "$12,350.00", dash_total)
check("and the Businesses tile shows the same figure", dash_total and dash_total in html,
      re.findall(r"\$[\d,]+\.\d\d", html))
m = re.search(r">Net<.*?(-?\$[\d,]+\.\d\d)", dash, re.S)
check("Net is built on it (no expenses here)", m and m.group(1) == "$12,350.00", m and m.group(1))
clients_page = c.get("/admin/clients").get_data(as_text=True)
m = re.search(r"J&amp;D Entertainment.*?text-emerald-300[^>]*>(\$[\d,]+\.\d\d)", clients_page, re.S)
check("the Clients list's Paid column leaves the tax out too", m and m.group(1) == "$12,350.00", m and m.group(1))
client_page = c.get(f"/admin/clients/{ids['client']}").get_data(as_text=True)
m = re.search(r"Total Revenue</p>\s*<p[^>]*>(\$[\d,]+\.\d\d)", client_page)
check("the client page's Total Revenue is the same reading", m and m.group(1) == "$12,350.00", m and m.group(1))
costs = c.get("/api/guidance/costs", headers={"Authorization": "Bearer test-key"}).get_json() or {}
paid = next((x.get("paid") for x in costs.get("clients", []) if x.get("name") == "J&D Entertainment"), None)
check("the API's paid is still cash in, tax and back tax included", paid == 13165.1, paid)
check("a business on its app that has not reported says so", "App not reporting" in html)
check("a business with nothing to count says so", "Not tracked" in html)
check("no tax numbers up front", "32093304155" not in html and "RT000000" not in html)
check("the list never asks an app", not hub_calls, hub_calls)
check("each tile opens its business", f'href="/admin/businesses/{ids["bbb"]}"' in html)
check("a logo from My Apps is drawn", f'/admin/apps/icon/{ids["site"]}' in html)

print("A business's page")
page = c.get(f"/admin/businesses/{ids['bbb']}").get_data(as_text=True)
check("carries the tax numbers", "32093304155" in page and "RT000000" in page)
check("and eSystems", "eSystems" in page and "Every return" in page)
check("and the same revenue as the list and the dashboard", dash_total and dash_total in page)
page = c.get(f"/admin/businesses/{ids['ehq']}").get_data(as_text=True)
check("an app's business is asked for its lifetime sales, briefly",
      len(hub_calls) == 1 and hub_calls[0][0] == "/api/hub/tax/sales" and hub_calls[0][2] <= 6, hub_calls)
check("from the day it was formed", hub_calls and hub_calls[0][1]["from"] == "2026-10-05", hub_calls)
check("and shows what it said, skipping a bad row", "$7,349.00" in page)
c.get(f"/admin/businesses/{ids['ehq']}")
check("a fresh answer is not asked for again", len(hub_calls) == 1, hub_calls)
html = c.get("/admin/businesses").get_data(as_text=True)
check("the list now shows the app's figure without asking", "$7,349.00" in html and len(hub_calls) == 1)
with application.app_context():
    e = db.session.get(Business, ids["ehq"])
    e.revenue_as_of = datetime.now(timezone.utc) - timedelta(hours=2)
    db.session.commit()
c.get(f"/admin/businesses/{ids['ehq']}")
check("an old answer is asked for again", len(hub_calls) == 2, hub_calls)

print("The logo")


def save(bid, **extra):
    with application.app_context():
        b = db.session.get(Business, bid)
        form = {"name": b.name, "short_name": b.short_name or "", "slug": b.slug,
                "sales_source": b.sales_source, "sales_tax_frequency": "quarterly",
                "taxable_share": "80", "is_active": "1",
                "formed_on": b.formed_on.isoformat() if b.formed_on else ""}
    form.update(extra)
    return c.post(f"/admin/businesses/{bid}/edit", data=form, content_type="multipart/form-data")


form_html = c.get(f"/admin/businesses/{ids['shelf']}/edit").get_data(as_text=True)
check("the form offers each app that has an icon", f'value="{ids["ehq_app"]}"' in form_html
      and f'value="{ids["bare"]}"' not in form_html)
r = save(ids["shelf"], logo_choice=str(ids["ehq_app"]))
with application.app_context():
    check("choosing an app's icon saves it", db.session.get(Business, ids["shelf"]).logo_app_id == ids["ehq_app"],
          r.status_code)
r = save(ids["shelf"], logo_upload=(io.BytesIO(PNG), "mark.png"))
with application.app_context():
    s = db.session.get(Business, ids["shelf"])
    check("an upload wins and clears the app's icon", s.logo_file and s.logo_app_id is None, (s.logo_file, s.logo_app_id))
    stored = s.logo_file
resp = c.get(f"/admin/businesses/{ids['shelf']}/logo")
check("the upload is served, locked down",
      resp.status_code == 200 and resp.headers.get("Content-Security-Policy", "").startswith("default-src 'none'")
      and resp.headers.get("X-Content-Type-Options") == "nosniff", (resp.status_code, dict(resp.headers)))
resp.close()
r = save(ids["shelf"], logo_upload=(io.BytesIO(b"MZ" * 50), "virus.exe"))
with application.app_context():
    check("a file that is not an image is refused", db.session.get(Business, ids["shelf"]).logo_file == stored)
r = save(ids["shelf"], logo_choice="none")
with application.app_context():
    s = db.session.get(Business, ids["shelf"])
    check("none clears it, file and all", s.logo_file is None and s.logo_app_id is None
          and not (pathlib.Path(TMP) / br.LOGO_DIR / stored).exists())
r = save(ids["shelf"], logo_choice=str(ids["bare"]))
check("an app with no icon cannot be chosen", r.status_code == 200 and "no icon" in r.get_data(as_text=True))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
