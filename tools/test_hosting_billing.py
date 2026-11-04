# -*- coding: utf-8 -*-
"""Hosting: a priced project with no mapping, and the fee Stripe actually bills.

docs/automation_gaps.md items 7 (the Hosting half) and 10. Proves:

  1. A priced project with no ServiceMapping and no cost reads "Not mapped",
     not "Fine", is counted on the tile and in the sidebar badge, and offers
     the press that maps it (the mapping form, with the project chosen).
  2. One that is mapped and simply cost nothing still reads "No cost
     recorded", and is not counted.
  3. Stripe's hosting items are read as a month (a $600 year is $50), only
     items whose product says hosting.
  4. "Billed $X/mo, agreed $Y/mo" is drawn once per client with the press
     that changes the subscription, which asks first; an agreed fee with no
     hosting subscription is flagged and offers Stripe; both are counted.
  5. The press sends Stripe one item moved to the agreed fee, kept on its
     cycle, with no proration.
  6. The badge never waits on Stripe: it reads the last answer only.

Run: python tools/test_hosting_billing.py
"""
import os
import pathlib
import re
import sys
import tempfile
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-hosting-billing-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Client, Project, ServiceProvider, ServiceMapping, User  # noqa: E402
import pm.hosting_routes as hosting  # noqa: E402
import hosting_billing  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


import stripe_service  # noqa: E402
stripe_service.get_hosting_revenue = lambda: {
    "collected": 0.0, "outstanding": 0.0, "paid_invoices": 0, "by_customer": {}}
COSTS = {}
hosting._costs_by_project = lambda months: ({pid: {months[-1]: a} for pid, a in COSTS.items()}, {})
hosting._railway_lifetime_by_project = lambda: {}
hosting._railway_all_time = lambda: {"amount": 0.0, "source": "invoices", "months": 0}


# A Stripe that answers from memory, the shape the SDK hands back.
class Obj(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


def sub(sid, customer, items, status="active"):
    return Obj(id=sid, customer=customer, status=status,
               items=Obj(data=[Obj(id=f"{sid}-item{i}", quantity=1,
                                   price=Obj(unit_amount=cents, currency="usd", nickname=None,
                                             product=product,
                                             recurring=Obj(interval=interval, interval_count=1)))
                               for i, (cents, interval, product) in enumerate(items)]))


PRODUCTS = {"prod_host": "Monthly Hosting & Data Storage", "prod_dev": "Development retainer"}
SUBS = [
    sub("sub_kuper", "cus_kuper", [(4000, "month", "prod_host")]),            # billed $40, agreed $50
    sub("sub_year", "cus_year", [(60000, "year", "prod_host")]),             # $600 a year: $50 a month
    sub("sub_dev", "cus_unbilled", [(150000, "month", "prod_dev")]),         # not hosting
    sub("sub_gone", "cus_unbilled", [(5000, "month", "prod_host")], status="canceled"),
]
MODIFIED = []
fake = SimpleNamespace(
    api_key="sk_test",
    Product=SimpleNamespace(retrieve=lambda pid: Obj(name=PRODUCTS[pid])),
    Subscription=SimpleNamespace(
        list=lambda **kw: SimpleNamespace(auto_paging_iter=lambda: iter(SUBS)),
        modify=lambda sid, **kw: MODIFIED.append((sid, kw))))
hosting_billing._stripe = lambda: fake

print("3. STRIPE'S HOSTING ITEMS, AS A MONTH")
data = hosting_billing.read()
check("the monthly item is $40 a month", data["cus_kuper"][0]["monthly"] == 40.0, data.get("cus_kuper"))
check("a $600 year is $50 a month", data["cus_year"][0]["monthly"] == 50.0, data.get("cus_year"))
check("a development retainer is not hosting, and a canceled sub bills nothing",
      "cus_unbilled" not in data, data.get("cus_unbilled"))

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    rail = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    db.session.add(rail)
    made = {}
    for name, customer, fee in (("Kuper", "cus_kuper", 50.0), ("Yearly", "cus_year", 50.0),
                                ("Unbilled", "cus_unbilled", 50.0), ("Unmapped", "cus_year", None)):
        client = Client.query.filter_by(stripe_customer_id=customer).first()
        if client is None:
            client = Client(name=name + " Co", email=f"{name}@example.test", stripe_customer_id=customer)
            db.session.add(client)
            db.session.flush()
        p = Project(name=name, client_id=client.id, hosting_fee=fee if fee is not None else 0.0,
                    hosting_cycle="monthly")
        db.session.add(p)
        db.session.flush()
        made[name] = p
    # Unmapped is priced at $25 on the Yearly client, so that client's
    # agreed total is $75 against $50 billed. Kuper, Yearly and Unbilled
    # are mapped; Unmapped is not.
    made["Unmapped"].hosting_fee = 25.0
    made["Yearly"].hosting_fee = 50.0
    for name in ("Kuper", "Yearly", "Unbilled"):
        db.session.add(ServiceMapping(provider_id=rail.id, resource_identifier=f"railway:{name}",
                                      project_id=made[name].id, client_id=made[name].client_id))
    db.session.commit()
    ids = {k: v.id for k, v in made.items()}
    boss_id = boss.id
COSTS.update({ids["Kuper"]: 10.0, ids["Yearly"]: 0.0, ids["Unbilled"]: 0.0, ids["Unmapped"]: 0.0})

print("\n1-2. NOT MAPPED IS ITS OWN BAND")
check("priced, no mapping, no cost: Not mapped", hosting._status(50.0, 0.0, mapped=False) == ("unmapped", "Not mapped"))
check("priced, mapped, no cost: still No cost recorded", hosting._status(50.0, 0.0, mapped=True) == ("fine", "No cost recorded"))
check("hosted free and unmapped is still free", hosting._status(0.0, 0.0, mapped=False)[0] == "free")
check("the band has a place in the order", "unmapped" in hosting.STATUS_ORDER)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

page = c.get("/admin/hosting/").data.decode("utf-8", "replace")
check("the page draws", "Not mapped" in page)
check("the unmapped row offers the mapping form with its project chosen",
      f"/admin/service-costs/mappings/new?project_id={ids['Unmapped']}" in page, re.findall(r"mappings/new[^\"]*", page))

print("\n4. BILLED AGAINST AGREED")
check("Kuper: billed $40.00, agreed $50.00", "Billed $40.00/mo, agreed $50.00/mo" in page)
check("the Yearly client's two projects agree $75.00 against $50.00 billed",
      "Billed $50.00/mo, agreed $75.00/mo" in page)
check("said once per client, not once per project", page.count("agreed $75.00/mo") == 1, page.count("agreed $75.00/mo"))
check("an agreed fee with no hosting subscription is flagged",
      "Agreed $50.00/mo, no hosting subscription in Stripe" in page)
check("and offers Stripe", "dashboard.stripe.com/customers/cus_unbilled" in page)
check("a difference offers the press, which asks first",
      "Change the subscription?" in page and page.count("data-bill-press") == 3, page.count("data-bill-press"))

tile = re.search(r"Needs a look.*?>(\d+)<", page, re.S)
counted = int(tile.group(1)) if tile else -1
check("the tile counts the unmapped project and the three clients' billing", counted == 4, counted)
presses = page.count("data-bill-press") + page.count("data-map-press") + page.count("/admin/contracts/new/hosting")
check("every counted row offers its press", presses == counted, (presses, counted))
with application.test_request_context():
    hosting._DUE_CACHE.update(at=0.0, rows=[])
    badge = hosting.increases_due_count()
check("the sidebar badge agrees with the tile", badge == counted, (badge, counted))

print("\n5. THE PRESS")
r = c.post(f"/admin/hosting/billing/{made['Kuper'].client_id}")
check("it redirects back", r.status_code == 302)
check("Stripe is sent one item at the agreed fee, on its cycle, with no proration",
      MODIFIED and MODIFIED[-1][0] == "sub_kuper"
      and MODIFIED[-1][1]["items"][0]["price_data"]["unit_amount"] == 5000
      and MODIFIED[-1][1]["items"][0]["price_data"]["recurring"]["interval"] == "month"
      and MODIFIED[-1][1]["proration_behavior"] == "none", MODIFIED)
before = len(MODIFIED)
c.post(f"/admin/hosting/billing/{made['Unbilled'].client_id}")
check("a client with no subscription is never sent anything", len(MODIFIED) == before)

print("\n7. ONE READING, TWO PLACES")
# The badge reads Stripe's last answer and the page a fresh one. When the two
# differ, the badge must still say what the page just drew: one function
# (hosting_rows) on one answer. In the fresh answer Kuper is billed the agreed
# $50, so nothing is counted for it; the last answer still says $40, which
# would count. The old code counted the badge from the last answer.
STALE = dict(hosting_billing._CACHE["data"])
FRESH = dict(STALE, cus_kuper=[dict(STALE["cus_kuper"][0], amount=50.0, monthly=50.0)])
real_current, real_snapshot = hosting_billing.current, hosting_billing.snapshot
hosting_billing.current = lambda ttl=300: FRESH
hosting_billing.snapshot = lambda app=None: STALE
hosting._DUE_CACHE.update(at=0.0, rows=[])
page = c.get("/admin/hosting/").data.decode("utf-8", "replace")
tile = re.search(r"Needs a look.*?>(\d+)<", page, re.S)
counted = int(tile.group(1)) if tile else -1
with application.test_request_context():
    badge = hosting.increases_due_count()
check("the page drew Kuper as billed what was agreed", "Billed $40.00/mo" not in page)
check("and the badge says the page's number, not the last answer's", badge == counted, (badge, counted))
hosting_billing.current, hosting_billing.snapshot = real_current, real_snapshot

print("\n8. THE PRESS ACTS IN PLACE")
check("the bill press is a live action",
      re.search(r"<form[^>]*billing/\d+[^>]*data-live-action", page) is not None)
check("inside a live region that is always drawn, with the tiles beside it",
      'data-live="hosting-rows"' in page and 'data-live="hosting-tiles"' in page)

print("\n6. THE BADGE NEVER WAITS ON STRIPE")
asked = []
hosting_billing._CACHE.update(at=0.0, data=None)
hosting_billing.read = lambda: asked.append(1)
with application.app_context():
    got = hosting_billing.snapshot(None)
check("with no last answer and no app, it reads nothing and says nothing", got is None and asked == [])

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
