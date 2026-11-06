# -*- coding: utf-8 -*-
"""Hosting takes in the vendor pages (docs/finances_plan.md item 9).

Proves:

  1. One tab row (Fees, Mappings, Railway months, Vendors) over every page of
     the section, the forms included, each page's content in the panel a tab
     press swaps, and the right tab current.
  2. CEO only: Hannah (CMO) is refused on every route of hosting_bp and
     service_costs_bp, GET and POST, and a refused POST changes nothing.
  3. The old Service costs address answers a 301 to Hosting (gated), and
     sync_all goes back to the Vendors tab, never to it. Every endpoint other
     pages url_for still resolves.
  4. The missing-vendor-bill check is one: the Railway months tab's count, the
     bills listed on its page and Needs attention are the same months, and the
     old months_missing_manual_costs is a reading of the same list. Recording
     the bill takes it off all three at once.
  5. A Railway account's month opens on the Railway months tab (old links to
     provider_monthly land there), the account and month are its query
     string, and a save comes back to the same month.
  6. The Vendors tab counts the vendors whose sync is in trouble, and those
     are the cards that say so; a vendor billed to another of Michael's
     businesses says whose, not "Built by Bean".
  7. Stale wording is gone from the section's code and pages.

Run: python tools/test_hosting_tabs.py
"""
import json
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-hostingtabs-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED", "MAIL_SYNC_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (  # noqa: E402
    db, Business, Client, Project, ProviderInvoice, ServiceCostEntry, ServiceMapping,
    ServiceProvider, User,
)
import provider_bills  # noqa: E402
from pm import attention_routes  # noqa: E402
import service_costs_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []

# Nothing here may reach a vendor.
service_costs_service.list_provider_resources = lambda provider: [
    {"id": "res-site", "label": "Tabs Site"}]
service_costs_service.sync_provider = lambda pid: (0, None)
import pm.service_costs_routes as scr  # noqa: E402
scr.list_provider_resources = service_costs_service.list_provider_resources
scr.sync_provider = service_costs_service.sync_provider


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def back(months):
    m = date.today().replace(day=1)
    for _ in range(months):
        m = (m - timedelta(days=1)).replace(day=1)
    return m


LAST, TWO, THREE = back(1), back(2), back(3)


class As:
    """A test client signed in as one person, the cached user cleared before
    every request (tools/test_workspace.py says why)."""

    def __init__(self, user_id):
        self.c = application.test_client()
        with self.c.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True

    def __getattr__(self, name):
        method = getattr(self.c, name)

        def call(*a, **kw):
            from flask import g, has_app_context
            if has_app_context():
                g.pop("_login_user", None)
            return method(*a, **kw)
        return call


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", last_name="Bean", role="ceo")
    hannah = User(username="hb", email="hb@example.test", first_name="Hannah", last_name="Bean", role="cmo")
    boss.set_password("password")
    hannah.set_password("password")
    ehq = Business(name="EntertainHQ LLC", slug="entertainhq")
    client = Client(name="Tabs Client", email="tabs@example.test")
    db.session.add_all([boss, hannah, ehq, client])
    db.session.flush()
    project = Project(name="Tabs Site", client_id=client.id, hosting_fee=50.0, phase="in_production",
                      hosting_cycle="monthly", created_at=datetime.now(timezone.utc))
    db.session.add(project)
    typed = ServiceProvider(name="railway", display_name="Railway",
                            credentials_json=json.dumps({"api_token": "x"}),
                            last_sync_at=datetime.now(timezone.utc))
    pulled = ServiceProvider(name="railway", display_name="Railway (EntertainHQ)",
                             credentials_json=json.dumps({"api_token": "x", "workspace_id": "ws"}),
                             account_business_id=ehq.id, last_sync_at=datetime.now(timezone.utc))
    broken = ServiceProvider(name="cloudflare", display_name="Cloudflare",
                             credentials_json="{}", sync_error="token refused",
                             last_sync_at=datetime.now(timezone.utc))
    flat = ServiceProvider(name="flat", display_name="Claude", credentials_json="{}",
                           monthly_cost=100.0, last_sync_at=datetime.now(timezone.utc))
    db.session.add_all([typed, pulled, broken, flat])
    db.session.flush()
    mapping = ServiceMapping(provider_id=typed.id, resource_identifier="res-site",
                             resource_label="Tabs Site", client_id=client.id, project_id=project.id)
    db.session.add(mapping)
    # Both accounts have cost since THREE months back. The typed one has
    # THREE's bill only, so TWO and LAST are missing; the pulled one has none,
    # so THREE and TWO are missing and LAST is its month of grace.
    for p in (typed, pulled):
        db.session.add(ServiceCostEntry(provider_id=p.id, resource_identifier="res-site",
                                        period_start=THREE, period_end=THREE + timedelta(days=27),
                                        raw_amount=10.0, allocated_amount=10.0))
    db.session.add(ProviderInvoice(provider_id=typed.id, period_month=THREE, amount=20.0))
    db.session.commit()
    BOSS, HANNAH = boss.id, hannah.id
    TYPED, PULLED, BROKEN, FLAT = typed.id, pulled.id, broken.id, flat.id
    MAPPING, PROJECT, CLIENT = mapping.id, project.id, client.id

ceo, cmo = As(BOSS), As(HANNAH)


def page(client, url):
    r = client.get(url)
    return r, r.data.decode("utf-8", "replace")


def tabs_of(html):
    nav = re.search(r'<nav data-keep="hosting-tabs" data-active="([^"]+)".*?</nav>', html, re.S)
    if not nav:
        return None, []
    return nav.group(1), re.findall(r'data-tab="([^"]+)"', nav.group(0))


print("1. One tab row over the whole section")
with application.test_request_context():
    from flask import url_for
    PAGES = [
        ("fees", url_for("hosting.hosting_index")),
        ("mappings", url_for("service_costs.mappings_list")),
        ("mappings", url_for("service_costs.mapping_create")),
        ("mappings", url_for("service_costs.mapping_edit", id=MAPPING)),
        ("railway", url_for("service_costs.railway_months")),
    ]
for want, url in PAGES:
    r, html = page(ceo, url)
    active, ids = tabs_of(html)
    check(f"{url} draws, under the tab row, with {want} current",
          r.status_code == 200 and active == want and ids == ["fees", "mappings", "railway"],
          (r.status_code, active, ids))
    check(f"{url} puts its content in the hosting panel", 'data-panel="hosting"' in html)
    check(f"{url} carries no back link to Expenses", "expenses" not in (re.search(
        r'id="pm-back".*?</', html, re.S) or re.search("", "")).group(0).lower())

print("2. CEO only, every route, GET and POST")
GETS = ["/admin/hosting/", "/admin/service-costs/", "/admin/service-costs/providers",
        "/admin/service-costs/providers/new", f"/admin/service-costs/providers/{TYPED}/edit",
        f"/admin/service-costs/providers/{TYPED}/monthly", "/admin/service-costs/railway",
        "/admin/service-costs/mappings", "/admin/service-costs/mappings/new",
        f"/admin/service-costs/mappings/{MAPPING}/edit",
        f"/admin/service-costs/api/resources/{TYPED}", "/admin/service-costs/api/costs-by-client",
        "/admin/service-costs/api/costs-by-provider"]
POSTS = [f"/admin/hosting/billing/{CLIENT}", "/admin/service-costs/providers/new",
         f"/admin/service-costs/providers/{TYPED}/edit", f"/admin/service-costs/providers/{FLAT}/delete",
         f"/admin/service-costs/providers/{TYPED}/sync", "/admin/service-costs/sync-all",
         f"/admin/service-costs/providers/{TYPED}/monthly",
         f"/admin/service-costs/providers/{TYPED}/monthly/automap",
         "/admin/service-costs/mappings/new", f"/admin/service-costs/mappings/{MAPPING}/edit",
         f"/admin/service-costs/mappings/{MAPPING}/delete"]
with application.test_request_context():
    refusal = url_for("admin_hub")  # never a money page: it would refuse again
for url in GETS:
    r = cmo.get(url)
    check(f"Hannah is refused GET {url}", r.status_code == 302 and r.headers["Location"].endswith(refusal),
          (r.status_code, r.headers.get("Location")))
for url in POSTS:
    r = cmo.post(url, data={"name": "aws", "provider_id": str(TYPED), "resource_identifier": "x",
                            "invoice_amount": "1", "month": THREE.strftime("%Y-%m")})
    check(f"Hannah is refused POST {url}", r.status_code == 302 and r.headers["Location"].endswith(refusal),
          (r.status_code, r.headers.get("Location")))
with application.app_context():
    check("a refused POST changed nothing",
          db.session.get(ServiceProvider, FLAT) is not None
          and db.session.get(ServiceMapping, MAPPING) is not None
          and ServiceProvider.query.count() == 4 and ServiceMapping.query.count() == 1
          and ProviderInvoice.query.count() == 1)
r = ceo.get("/admin/hosting/")
check("the CEO is let in", r.status_code == 200, r.status_code)

print("3. The old address, and where Sync all lands")
r = ceo.get("/admin/service-costs/")
check("/admin/service-costs/ is a 301 to Hosting",
      r.status_code == 301 and r.headers["Location"].endswith("/admin/hosting/"),
      (r.status_code, r.headers.get("Location")))
r = ceo.post("/admin/service-costs/sync-all")
check("Sync all comes back to the Vendors page",
      r.status_code == 302 and r.headers["Location"].endswith("/admin/vendors/"),
      r.headers.get("Location"))
r = ceo.post("/admin/service-costs/sync-all", data={"next": "/admin/expenses/"})
check("or to the admin page it was pressed on", r.headers.get("Location", "").endswith("/admin/expenses/"),
      r.headers.get("Location"))
r = ceo.post("/admin/service-costs/sync-all", data={"next": "https://example.com/"})
check("never off the board", r.headers.get("Location", "").endswith("/admin/vendors/"),
      r.headers.get("Location"))
with application.test_request_context():
    for endpoint, kw in (("service_costs.providers_list", {}), ("service_costs.provider_edit", {"id": 1}),
                         ("service_costs.mappings_list", {}), ("service_costs.mapping_create", {}),
                         ("service_costs.provider_monthly", {"id": 1}), ("service_costs.sync_all", {}),
                         ("service_costs.service_costs_dashboard", {}), ("hosting.hosting_index", {}),
                         ("service_costs.railway_months", {})):
        try:
            url_for(endpoint, **kw)
            ok = True
        except Exception as e:  # noqa: BLE001
            ok = e
        check(f"{endpoint} still resolves", ok is True, ok)
src = "\n".join(p.read_text(encoding="utf-8") for p in
                list((ROOT / "templates").rglob("*.html")) + list((ROOT / "pm").glob("*.py")))
check("nothing links to the old Service costs address any more",
      src.count("service_costs.service_costs_dashboard") == 0)

print("4. One missing-bill check, three places")
fmt = lambda ms: [m.strftime("%Y-%m") for m in ms]  # noqa: E731
with application.app_context():
    shared = {b["provider"].id: fmt(b["missing"]) for b in provider_bills.missing_bills()}
    attention = {b["provider"].id: fmt(b["missing"]) for b in attention_routes._bills_to_enter(force=True)}
check("the shared list: typed misses TWO and LAST, pulled misses THREE and TWO",
      shared == {TYPED: fmt([TWO, LAST]), PULLED: fmt([THREE, TWO])}, shared)
check("Needs attention lists the same months", attention == shared, (attention, shared))
check("the second copy of the check is gone", not hasattr(scr, "months_missing_manual_costs"))
r, html = page(ceo, "/admin/service-costs/railway")
count = re.search(r'data-count="railway"[^>]*>([^<]*)<', html)
check("the Railway months tab counts the missing months (4)", count and count.group(1).strip() == "4",
      count and count.group(1))
listed = sorted(int(x) for x in re.findall(r'data-missing-bill="(\d+)"', html))
check("its page lists both accounts' bills", listed == sorted([TYPED, PULLED]), listed)
r, html = page(ceo, "/admin/attention/")
check("Needs attention shows the same two vendors' bills",
      html.count("invoice not recorded") == 2, html.count("invoice not recorded"))

print("5. A Railway month lives on the Railway months tab")
r = ceo.get(f"/admin/service-costs/providers/{TYPED}/monthly?month={LAST:%Y-%m}")
check("an old link to a Railway account's month lands on the tab",
      r.status_code == 302 and f"/admin/service-costs/railway?provider={TYPED}&month={LAST:%Y-%m}"
      in r.headers["Location"], r.headers.get("Location"))
r, html = page(ceo, f"/admin/service-costs/railway?provider={PULLED}&month={TWO:%Y-%m}")
check("the account and month are the query string",
      r.status_code == 200 and "Railway (EntertainHQ), " + TWO.strftime("%B %Y") in html,
      r.status_code)
check("the bar applies itself", 'x-data="liveFilter()"' in html and "data-live-filters" in html)
check("the month says which months have no bill", f"{TWO:%b %Y} (no bill)" in html)
r, html = page(ceo, "/admin/service-costs/railway")
check("the tab opens on Built by Bean's own account, last month",
      "Railway, " + LAST.strftime("%B %Y") in html)
r = ceo.post(f"/admin/service-costs/providers/{TYPED}/monthly",
             data={"month": LAST.strftime("%Y-%m"), "amt:res-site": "12.50",
                   "lbl:res-site": "Tabs Site", "invoice_amount": "1,020.00"})
check("a save comes back to the same month on the tab",
      r.status_code == 302 and f"provider={TYPED}&month={LAST:%Y-%m}" in r.headers["Location"],
      r.headers.get("Location"))
with application.app_context():
    inv = ProviderInvoice.query.filter_by(provider_id=TYPED, period_month=LAST).first()
    check("the bill is recorded, commas and all", inv is not None and inv.amount == 1020.0,
          inv and inv.amount)
    after = {b["provider"].id: fmt(b["missing"]) for b in attention_routes._bills_to_enter()}
    check("Needs attention drops it at once, not after its cache", after.get(TYPED) == fmt([TWO]), after)
r, html = page(ceo, "/admin/service-costs/railway")
count = re.search(r'data-count="railway"[^>]*>([^<]*)<', html)
check("and the tab count with it (3)", count and count.group(1).strip() == "3", count and count.group(1))

print("6. Vendors (its own page since 2026-11-05, tools/test_vendors_page.py)")
r = ceo.get("/admin/service-costs/providers")
check("the old Vendors tab lands on the Vendors page", r.status_code == 301
      and r.headers["Location"].endswith("/admin/vendors/"), r.headers.get("Location"))
r, html = page(ceo, "/admin/vendors/")
troubled = re.findall(r'data-account="(\d+)"(?:(?!data-account=).)*?data-trouble', html, re.S)
check("the account whose sync failed is the one that says so", troubled == [str(BROKEN)], troubled)
card = re.search(rf'data-account="{PULLED}".*?data-payer>\s*([^<]+?)\s*</span>', html, re.S)
check("an account of EntertainHQ's says so", card and card.group(1).strip() == "EntertainHQ LLC",
      card and card.group(1))
# A Railway account's months are Hosting's Railway months tab; the Vendors page
# is read only (2026-11-05) and carries no Months press.

print("7. Stale wording")
OWN = [ROOT / "pm" / "hosting_routes.py", ROOT / "pm" / "service_costs_routes.py",
       ROOT / "provider_bills.py"] + list((ROOT / "templates" / "pm" / "hosting").rglob("*.html")) \
    + list((ROOT / "templates" / "pm" / "service_costs").rglob("*.html"))
BANNED = ["reports no money", "no billing api", "becomes an expense", "writes an expense",
          "books an expense", "and its expense", "monthly costs page", "service providers",
          "resource mappings", chr(0x2014)]
for path in OWN:
    text = path.read_text(encoding="utf-8").lower()
    hits = [b for b in BANNED if b in text]
    check(f"{path.relative_to(ROOT)} is free of the old wording", not hits, hits)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
